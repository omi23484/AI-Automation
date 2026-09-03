/* =============================================================================
   NetPulse — SQL Server schema (001)

   Target from the sizing decision: thousands of interfaces, 100M+ samples,
   growing. One clustered fact table plus a daily rollup for fleet-wide views.

   Deliberately NOT here: month partitioning (a retention feature, and retention
   is undecided), an hourly rollup tier, and a dirty-set table. A clustered index
   on (InterfaceId, TsUtc) already answers single-link range queries without them,
   and each can be added later without reshaping anything.

   NOT YET EXECUTED. No SQL Server instance was available where this was written,
   so this script has been reviewed but never run. Run it against an empty
   database and expect to correct small things before trusting it.
   ============================================================================= */

/* -------------------------------------------------------------------- entities */
CREATE TABLE dbo.Site (
  SiteId        int IDENTITY(1,1) NOT NULL CONSTRAINT PK_Site PRIMARY KEY,
  Name          nvarchar(128) NOT NULL CONSTRAINT UQ_Site_Name UNIQUE,
  Region        nvarchar(64)  NULL,
  TimeZoneId    nvarchar(64)  NOT NULL CONSTRAINT DF_Site_Tz DEFAULT 'India Standard Time',
  CreatedUtc    datetime2(0)  NOT NULL CONSTRAINT DF_Site_Created DEFAULT SYSUTCDATETIME()
);
GO

CREATE TABLE dbo.Device (
  DeviceId      int IDENTITY(1,1) NOT NULL CONSTRAINT PK_Device PRIMARY KEY,
  SiteId        int NOT NULL CONSTRAINT FK_Device_Site REFERENCES dbo.Site(SiteId),
  Hostname      nvarchar(255) NOT NULL,
  Vendor        nvarchar(64)  NULL,
  Model         nvarchar(64)  NULL,
  CreatedUtc    datetime2(0)  NOT NULL CONSTRAINT DF_Device_Created DEFAULT SYSUTCDATETIME(),
  CONSTRAINT UQ_Device_Hostname UNIQUE (Hostname)
);
GO

/* The atomic monitored unit. InterfaceId is internal and stable — deliberately
   never the SNMP ifIndex, which renumbers on a line-card change and would silently
   re-point history at the wrong port. */
CREATE TABLE dbo.Interface (
  InterfaceId     bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_Interface PRIMARY KEY,
  DeviceId        int NOT NULL CONSTRAINT FK_Interface_Device REFERENCES dbo.Device(DeviceId),
  Name            nvarchar(255) NOT NULL,
  Alias           nvarchar(255) NULL,
  IfIndex         int NULL,                       -- correlation only, never identity
  Class           nvarchar(32)  NOT NULL CONSTRAINT DF_Interface_Class DEFAULT 'WAN',
  BusinessImpact  nvarchar(16)  NOT NULL CONSTRAINT DF_Interface_Impact DEFAULT 'Medium',
  ScopeKey        nvarchar(64)  NULL,             -- reserved: per-team/customer scoping
  FirstSeenUtc    datetime2(0) NULL,
  LastSeenUtc     datetime2(0) NULL,
  State           nvarchar(16)  NOT NULL CONSTRAINT DF_Interface_State DEFAULT 'active',
  CONSTRAINT UQ_Interface_DeviceName UNIQUE (DeviceId, Name),
  CONSTRAINT CK_Interface_Impact CHECK (BusinessImpact IN ('Critical','High','Medium','Low'))
);
GO
CREATE INDEX IX_Interface_Scope ON dbo.Interface(ScopeKey) INCLUDE (DeviceId, Name);
GO

/* Speed, class and impact change over time, and analytics must use the value in
   force at the sample's timestamp — a 1G→10G upgrade must not rewrite last year's
   utilisation. Effective-dated rows; ValidToUtc NULL means "still in force". */
CREATE TABLE dbo.InterfaceAttributeHistory (
  Id            bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_IfAttrHist PRIMARY KEY,
  InterfaceId   bigint NOT NULL CONSTRAINT FK_IfAttrHist_Interface REFERENCES dbo.Interface(InterfaceId),
  Attribute     nvarchar(32) NOT NULL,            -- 'speed_bps' | 'class' | 'business_impact'
  Value         nvarchar(128) NOT NULL,
  ValidFromUtc  datetime2(0) NOT NULL,
  ValidToUtc    datetime2(0) NULL,
  CONSTRAINT CK_IfAttrHist_Range CHECK (ValidToUtc IS NULL OR ValidToUtc > ValidFromUtc)
);
GO
CREATE INDEX IX_IfAttrHist_Lookup ON dbo.InterfaceAttributeHistory(InterfaceId, Attribute, ValidFromUtc) INCLUDE (Value, ValidToUtc);
GO

/* ------------------------------------------------------------------ provenance */
CREATE TABLE dbo.UploadBatch (
  BatchId          uniqueidentifier NOT NULL CONSTRAINT PK_UploadBatch PRIMARY KEY
                     CONSTRAINT DF_UploadBatch_Id DEFAULT NEWSEQUENTIALID(),
  UploadedByUserId nvarchar(450) NOT NULL,        -- matches AspNetUsers.Id
  UploadedUtc      datetime2(0) NOT NULL CONSTRAINT DF_UploadBatch_At DEFAULT SYSUTCDATETIME(),
  SourceType       nvarchar(32) NOT NULL CONSTRAINT DF_UploadBatch_Src DEFAULT 'xlsx',
  OriginalFilename nvarchar(400) NOT NULL,
  Sha256           binary(32) NOT NULL,
  RowCount         int NOT NULL,
  AcceptedCount    int NOT NULL CONSTRAINT DF_UploadBatch_Acc DEFAULT 0,
  DuplicateCount   int NOT NULL CONSTRAINT DF_UploadBatch_Dup DEFAULT 0,
  CoverageFromUtc  datetime2(0) NULL,
  CoverageToUtc    datetime2(0) NULL,
  Status           nvarchar(24) NOT NULL CONSTRAINT DF_UploadBatch_Status DEFAULT 'pending',
  ColumnMapJson    nvarchar(max) NULL,
  CONSTRAINT CK_UploadBatch_Status CHECK (Status IN ('pending','committed','failed','superseded'))
);
GO
/* Re-uploading the same workbook must be recognised, not silently double-counted. */
CREATE UNIQUE INDEX UQ_UploadBatch_Sha ON dbo.UploadBatch(Sha256) WHERE Status = 'committed';
GO

/* ----------------------------------------------------------------------- facts
   Append-only. The clustered key leads with InterfaceId so a single link's range
   scan is contiguous, and TsUtc is the partitioning column. */
CREATE TABLE dbo.Sample (
  InterfaceId  bigint       NOT NULL,
  TsUtc        datetime2(0) NOT NULL,
  TxBps        float        NULL,
  RxBps        float        NULL,
  PeakTxBps    float        NULL,
  PeakRxBps    float        NULL,
  SpeedTxBps   bigint       NULL,   -- capacity in force at TsUtc, denormalised
  SpeedRxBps   bigint       NULL,
  UtilPct      float        NULL,   -- max(tx/speedTx, rx/speedRx); NULL when unknowable
  PeakUtilPct  float        NULL,
  BatchId      uniqueidentifier NOT NULL,
  QualityFlags tinyint      NOT NULL CONSTRAINT DF_Sample_Flags DEFAULT 0,
                                    -- bit0 invalid(negative)  bit1 over-capacity
  CONSTRAINT PK_Sample PRIMARY KEY CLUSTERED (InterfaceId, TsUtc),
  CONSTRAINT FK_Sample_Interface FOREIGN KEY (InterfaceId) REFERENCES dbo.Interface(InterfaceId),
  CONSTRAINT FK_Sample_Batch FOREIGN KEY (BatchId) REFERENCES dbo.UploadBatch(BatchId)
) WITH (DATA_COMPRESSION = PAGE);
GO

/* Maintenance windows are NOT stamped onto samples. That mistake was made in the
   browser build: the flag was written at upload time and never re-evaluated, so a
   window deleted later left its samples excluded from the chart forever while the
   audit export still listed them. Exclusion is evaluated at query time against
   this table, in both directions. */
CREATE TABLE dbo.MaintenanceWindow (
  Id           int IDENTITY(1,1) NOT NULL CONSTRAINT PK_MaintWindow PRIMARY KEY,
  Scope        nvarchar(16) NOT NULL,             -- 'all' | 'device' | 'interface'
  DeviceId     int    NULL CONSTRAINT FK_Maint_Device REFERENCES dbo.Device(DeviceId),
  InterfaceId  bigint NULL CONSTRAINT FK_Maint_Interface REFERENCES dbo.Interface(InterfaceId),
  StartUtc     datetime2(0) NOT NULL,
  EndUtc       datetime2(0) NOT NULL,
  Reason       nvarchar(400) NULL,
  CreatedByUserId nvarchar(450) NOT NULL,
  CreatedUtc   datetime2(0) NOT NULL CONSTRAINT DF_Maint_Created DEFAULT SYSUTCDATETIME(),
  CONSTRAINT CK_Maint_Range CHECK (EndUtc > StartUtc),
  CONSTRAINT CK_Maint_Scope CHECK (Scope IN ('all','device','interface'))
);
GO
CREATE INDEX IX_Maint_Range ON dbo.MaintenanceWindow(StartUtc, EndUtc) INCLUDE (Scope, DeviceId, InterfaceId);
GO

/* ---------------------------------------------------------------- daily rollup
   Earns its place for fleet-wide views only: those scan every link over the whole
   window, which is the one query the clustered index cannot serve cheaply. A
   single link's chart reads raw and is fast.

   ponytail: rebuilt by one nightly full MERGE, not incrementally. At ~100M
   samples that is a few minutes of a maintenance window. Move to an incremental
   dirty-set rebuild when that stops being true, or when rollups must be fresh
   within the day. */
CREATE TABLE dbo.RollupDay (
  InterfaceId     bigint NOT NULL,
  BucketDate      date   NOT NULL,
  SampleCount     int    NOT NULL,
  AvgUtil         float  NULL,
  MaxUtil         float  NULL,
  MinUtil         float  NULL,
  P95Util         float  NULL,   -- the series the forecast consumes
  P99Util         float  NULL,
  BusinessHoursP95Util float NULL,
  StateSecondsNormal   int NOT NULL CONSTRAINT DF_RD_Normal   DEFAULT 0,
  StateSecondsWarning  int NOT NULL CONSTRAINT DF_RD_Warning  DEFAULT 0,
  StateSecondsHigh     int NOT NULL CONSTRAINT DF_RD_High     DEFAULT 0,
  StateSecondsCritical int NOT NULL CONSTRAINT DF_RD_Critical DEFAULT 0,
  ExcludedCount   int NOT NULL CONSTRAINT DF_RD_Excluded DEFAULT 0,
  ComputedUtc     datetime2(0) NOT NULL CONSTRAINT DF_RD_Computed DEFAULT SYSUTCDATETIME(),
  CONSTRAINT PK_RollupDay PRIMARY KEY CLUSTERED (InterfaceId, BucketDate)
);
GO

/* ------------------------------------------------------------- derived results */
CREATE TABLE dbo.LinkAnalytics (
  InterfaceId    bigint NOT NULL CONSTRAINT PK_LinkAnalytics PRIMARY KEY,
  ComputedUtc    datetime2(0) NOT NULL,
  WindowFromUtc  datetime2(0) NOT NULL,
  WindowToUtc    datetime2(0) NOT NULL,
  SampleCount    bigint NOT NULL,
  AvgUtil        float NULL,
  P95Util        float NULL,
  P99Util        float NULL,
  MaxUtil        float NULL,
  RiskScore      int   NULL,
  VerdictLevel   nvarchar(16) NULL,
  VerdictTitle   nvarchar(200) NULL,
  ForecastJson   nvarchar(max) NULL,   -- ForecastResult, verbatim
  RiskFactorsJson nvarchar(max) NULL,
  EngineVersion  nvarchar(32) NOT NULL -- stamped so a past report is reproducible
);
GO

/* ------------------------------------------------------------------ audit trail
   Append-only: no UPDATE or DELETE grant is issued on this table to any
   application role, so even an administrator cannot rewrite it. */
CREATE TABLE dbo.AuditEvent (
  Id          bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_AuditEvent PRIMARY KEY,
  OccurredUtc datetime2(0) NOT NULL CONSTRAINT DF_Audit_At DEFAULT SYSUTCDATETIME(),
  UserId      nvarchar(450) NULL,
  UserName    nvarchar(256) NULL,
  Action      nvarchar(64)  NOT NULL,
  TargetType  nvarchar(64)  NULL,
  TargetId    nvarchar(128) NULL,
  Detail      nvarchar(max) NULL,
  SourceIp    nvarchar(45)  NULL
);
GO
CREATE INDEX IX_Audit_Time ON dbo.AuditEvent(OccurredUtc DESC) INCLUDE (Action, UserName);
GO

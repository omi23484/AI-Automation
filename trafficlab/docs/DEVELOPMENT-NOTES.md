# Development notes (not needed to use the tool)

Historical notes from building and testing this project against one specific set of data.

## Data provenance: what real data was (not) available
Searched the account's repos/sessions that this session can reach. **No real traffic time series exists there**: all sample datasets
(`HTML/samples/sla/*`, NetPulse goldens, ACI synth) are labelled synthetic. Real device `show` output exists only as `HTML/samples/real/*.log`
(IOS-XE router + NX-OS leaf; per that repo's README they derive from public ntc-templates fixtures). Those are single snapshots with no collection
timestamp, and at least one is internally impossible (338,297,234 packets vs 728,401,053 bytes = ~2 B/packet), so they were edited/anonymised:
usable as parser fixtures for Phase 2, not as telemetry. Lab-device sessions ran on the user's own machine ("bridge") and are not reachable from here.


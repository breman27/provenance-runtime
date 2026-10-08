# Sensor service

The service processes batches of integer sensor readings for a dashboard.
Outputs must stay between 0 and 100 inclusive. Inputs already in that interval
must be preserved. Values below 0 map to 0, and values above 100 map to 100.

Run `python service.py` to process one batch and emit one JSON log per reading.
The deployed implementation is `src/clamp.py`. Each collected run identifies
its immutable Git revision and the SHA-256 of the source actually executed.

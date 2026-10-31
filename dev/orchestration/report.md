# Orchestrator Telemetry Series Evaluation Report

**Total Series Evaluated**: 10  
**Passed**: 10 | **Failed**: 0  
**Pass Rate**: 100.0%  

## Evaluated Series Matrix

| Series | Description | Expected Trigger | Actual Trigger | Status |
| :--- | :--- | :--- | :--- | :--- |
| **1. Steady Workload** | Normal battery (75%), CPU 25%, RAM 35% | `None` | `None` | **PASS** |
| **2. Slow Battery Drain** | Linear discharge projecting TTE < 900s | `predicted` | `predicted` | **PASS** |
| **3. Sudden Battery Drop** | Battery drops to 14% (<20% threshold) | `low_battery` | `low_battery` | **PASS** |
| **4. CPU Pressure Spike** | CPU > 90% sustained for 21 seconds (>20s) | `cpu_pressure` | `cpu_pressure` | **PASS** |
| **5. Memory Pressure Climb** | RAM > 90% sustained for 21 seconds (>20s) | `memory_pressure` | `memory_pressure` | **PASS** |
| **6. Connectivity Lost** | Link down (100% loss) for 3.5s (>3s window) | `connectivity_lost` | `connectivity_lost` | **PASS** |
| **7. Charger Connected** | Charger connected at 18% suppresses low_battery | `Suppressed` | `Suppressed` | **PASS** |
| **8. Noisy Battery Readings** | Erratic readings rejected by OLS noise filter | `Rejected` | `Rejected` | **PASS** |
| **9. Transient CPU Spike** | CPU spike lasting 8s (<20s window) drops back | `None` | `None` | **PASS** |
| **10. Candidate Selection** | Low battery trigger produces target recommendation | `dev-target (MIGRATE)` | `dev-target (MIGRATE)` | **PASS** |

## Tuning and Hysteresis Highlights
- **Sliding Windows**: Continuous 20s window on CPU/RAM avoid spurious load spikes.
- **Connectivity Loss**: Detects complete packet loss or zero throughput sustained for 3.0 seconds.
- **OLS Battery Filter**: Rejects erratic telemetry (R^2 < 0.6) and suppresses alerts on charger.
- **Action Cooldown**: Enforces 2-minute quiet period per workload to avoid recommendation storms.

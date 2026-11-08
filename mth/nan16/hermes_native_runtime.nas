; Persistent HERMES guest loaded by real canonical NaN0S C runtime.
; This image is assembled as NaN16 words with LABELS emitted by nmk.awk.
; The stable load entry and n16_server_exchange are inert compatibility stubs:
; N16T protocol runs in the existing separate N16T guest VM/pool, not here.
main:
HALT
n16_server_exchange:
HALT
.include "hermes_lease.nas"
.include "hermes_nannet_route.nas"
.include "mth_hierarchy_route.nas"
.include "mth_integer.nas"
; Full user-provided connector uses the same HERMES native lease, route,
; SHA-256, four-class NaN16DE codec, MTH tool allowlist and native NMP ledger.
; This image is assembled as a single guest; no host-language math or codec.
.include "mth_jahs_gate.nas"
.include "hermes_n16bridge.nas"
.include "runner_task.nas"
.include "hermes_tooltab.nas"
.include "hermes_connector.nas"

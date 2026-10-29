#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
script=$repo_root/downloads/install-mglogwh.sh
suite=$(mktemp -d /tmp/habang-installer-tests.XXXXXXXX)
mkdir "$suite/bin"
cat > "$suite/bin/sudo" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$CASE_ROOT/calls"
case $1 in
  -v|apt-get|mount) exit 0 ;;
  test) [[ $SCENARIO == existing ]]; exit ;;
  bash)
    if [[ $2 == */MGlogWH-ControlRoom/* ]]; then
      [[ $SCENARIO != room-failure ]] || exit 1
      touch "$CASE_ROOT/room"
    fi
    exit 0 ;;
  /usr/bin/python3)
    case $3 in
      validate) exit 0 ;;
      capability) [[ $SCENARIO != capability-failure ]]; exit ;;
      status)
        if [[ $SCENARIO == not-running ]]; then echo '{"state":"FAILED"}'; else echo '{"state":"RUNNING"}'; fi
        exit 0 ;;
    esac ;;
  systemctl)
    case $2 in
      is-active)
        if [[ $* == *mglogwh-controlroom.service* ]]; then [[ -f $CASE_ROOT/room ]]; exit; fi
        [[ $SCENARIO == existing || -f $CASE_ROOT/started ]]; exit ;;
      start) touch "$CASE_ROOT/started"; [[ $SCENARIO != start-failure ]]; exit ;;
      stop) touch "$CASE_ROOT/stopped"; exit 0 ;;
      enable) touch "$CASE_ROOT/enabled"; exit 0 ;;
    esac ;;
esac
echo "Unexpected sudo action: $*" >&2
exit 99
MOCK
cat > "$suite/bin/git" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ $1 == init ]]; then mkdir -p "$3"; exit; fi
if [[ ${3:-} == rev-parse ]]; then
  case $2 in
    */MGlogWH) echo 5cb573ac5402ca7580fb4c8e0a3f30576a5d38d2 ;;
    */MGlogWH-ControlRoom) echo 5f67113e7f9eea9c12d3105f42ae137723ab2c3e ;;
    */libbpf-bootstrap) echo d5f36b8ff051c78035696da31e673602c266d93c ;;
    *) exit 99 ;;
  esac
fi
MOCK
cat > "$suite/bin/curl" <<'MOCK'
#!/usr/bin/env bash
[[ $SCENARIO != http-failure ]]
MOCK
printf '#!/usr/bin/env bash\nexit 0\n' > "$suite/bin/make"
cp "$suite/bin/make" "$suite/bin/mountpoint"
cp "$suite/bin/make" "$suite/bin/sleep"
chmod +x "$suite/bin/"*
for scenario in success existing capability-failure start-failure not-running room-failure http-failure; do
  case_root=$suite/$scenario
  mkdir "$case_root"
  status=0
  PATH="$suite/bin:$PATH" CASE_ROOT="$case_root" SCENARIO="$scenario" bash "$script" > "$case_root/output" 2>&1 || status=$?
  if [[ $scenario == success || $scenario == existing ]]; then
    [[ $status == 0 && -f $case_root/enabled && ! -f $case_root/stopped ]] || { cat "$case_root/output"; exit 1; }
    grep -Fq '[OK] Collector is RUNNING' "$case_root/output"
    if [[ $scenario == existing ]]; then
      ! grep -q 'install-ubuntu.sh' "$case_root/calls"
    fi
  else
    [[ $status != 0 && ! -f $case_root/enabled ]] || { cat "$case_root/output"; exit 1; }
    ! grep -Fq '[OK]' "$case_root/output"
    if [[ $scenario != capability-failure ]]; then [[ -f $case_root/stopped ]]; fi
  fi
  echo "PASS Linux orchestration: $scenario"
done
printf 'Seven mocked Linux orchestration cases passed. No packages, services or system configuration were changed. Logs: %s\n' "$suite"

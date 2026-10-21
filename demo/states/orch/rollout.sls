# Demo orchestration: update the rovers, then the dock. The dock's calibration state fails on
# purpose (see dock.sls), so this shows what a failed step looks like.
rovers-answer:
  salt.function:
    - name: test.ping
    - tgt: 'rover-*'

rovers-motd:
  salt.state:
    - tgt: 'rover-*'
    - sls: motd
    - require:
      - salt: rovers-answer

dock-calibration:
  salt.state:
    - tgt: dock-01
    - sls: dock
    - require:
      - salt: rovers-motd

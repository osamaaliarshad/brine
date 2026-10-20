# Fails on purpose, so the demo shows what a failed state run looks like in brine.
calibrate-arm:
  cmd.run:
    - name: echo "arm not homed" >&2; exit 1

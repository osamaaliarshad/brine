# Installs rover-agent at a chosen version, up or down, from the packages the master serves:
#   state.apply agent pillar='{"agent_version": "2.4.1"}'
rover-agent:
  pkg.installed:
    - sources:
      - rover-agent: salt://debs/rover-agent_{{ pillar.get('agent_version', '2.4.1') }}_all.deb
    # Without it, apt-get won't go back to an older version.
    - force_yes: True

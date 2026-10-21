# Installs rover-agent at a chosen version, up or down, from the packages the master serves:
#   state.apply agent pillar='{"agent_version": "2.4.1"}'
rover-agent:
  pkg.installed:
    - sources:
      - rover-agent: salt://rover-agent_{{ pillar.get('agent_version', '2.4.1') }}_all.deb?saltenv=debs
    # Going down a version, apt-get stops ("Packages were downgraded and -y was used without
    # --allow-downgrades"), and only pkg.upgrade takes allow_downgrades. This passes --force-yes.
    - force_yes: True

# A tiny state so the demo has real state runs to show.
/etc/motd:
  file.managed:
    - contents: |
        {{ grains['id'] }} is managed by Salt (site {{ grains.get('site', 'unknown') }}).

# Demo reactor: when a minion (re)starts, sync its custom grains modules.
sync-grains:
  local.saltutil.sync_grains:
    - tgt: {{ data['id'] }}

schedule:
  __mine_interval: {enabled: true, function: mine.update, jid_include: true, maxrunning: 2,
    minutes: 60, name: __mine_interval, return_job: false, run: true, run_on_start: true,
    splay: null}
  extract_hardware_metrics:
    args: [hardware_metrics]
    enabled: true
    function: state.apply
    jid_include: true
    maxrunning: 1
    name: extract_hardware_metrics
    seconds: '${MINION_HARDWARE_METRICS_EXTRACTION_DELAY}' 
    splay: 3

from cairn import scheduler


def test_resolve_invocation_includes_sync_and_abspath():
    argv = scheduler.resolve_invocation("config.yaml", "fleet")
    assert "sync" in argv
    assert "--mode" in argv and "fleet" in argv
    # config path is made absolute
    idx = argv.index("-c")
    assert argv[idx + 1].startswith("/") or ":" in argv[idx + 1]  # unix or windows abspath


def test_launchd_plist_contents():
    plist = scheduler.generate_launchd_plist(["/usr/local/bin/cairn", "sync"], 3600, "/tmp/c.log")
    assert "com.cairn.sync" in plist
    assert "<integer>3600</integer>" in plist
    assert "<string>/usr/local/bin/cairn</string>" in plist
    assert "/tmp/c.log" in plist


def test_systemd_units():
    svc = scheduler.generate_systemd_service(["/usr/local/bin/cairn", "-c", "/etc/cairn.yaml", "sync"])
    assert "ExecStart=/usr/local/bin/cairn -c /etc/cairn.yaml sync" in svc
    assert "IOSchedulingClass=idle" in svc  # low-resource
    timer = scheduler.generate_systemd_timer(1800)
    assert "OnUnitActiveSec=1800s" in timer
    assert "WantedBy=timers.target" in timer


def test_cron_line_minute_and_hour():
    line_min = scheduler.generate_cron_line(["cairn", "sync"], 600)  # 10 min
    assert line_min.startswith("*/10 * * * *")
    assert "cairn-managed" in line_min
    line_hr = scheduler.generate_cron_line(["cairn", "sync"], 7200)  # 2 h
    assert line_hr.startswith("0 */2 * * *")


def test_windows_create_argv():
    argv = scheduler.windows_create_argv(["C:\\cairn.exe", "sync"], 3600)
    assert argv[:4] == ["schtasks", "/Create", "/TN", "Cairn"]
    assert "/MO" in argv and "60" in argv  # 60 minutes


def test_resolve_invocation_drift_command_omits_mode():
    # The scheduled drift-digest hook runs `drift`, read-only; --mode is sync-only.
    argv = scheduler.resolve_invocation("config.yaml", "fleet", command="drift")
    assert "drift" in argv
    assert "sync" not in argv
    assert "--mode" not in argv


def test_quote_paths_with_spaces():
    cmd = scheduler._cmdline(["/Applications/My App/cairn", "sync"])
    assert '"/Applications/My App/cairn"' in cmd

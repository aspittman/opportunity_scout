from unittest.mock import Mock
import main
from opportunityscout.services.scheduler import LocalScheduler


def test_scheduler_has_single_owner_and_independent_due_dispatch(tmp_path):
    research = Mock()
    lock_path = tmp_path / 'scheduler.lock'
    first = LocalScheduler(research, lock_path)
    second = LocalScheduler(research, lock_path)
    try:
        assert first.start() is True
        assert second.start() is False
        dispatch = first.scheduler.get_job('research')
        assert dispatch.kwargs == {'due_only': True}
        assert dispatch.max_instances == 1
        assert first.scheduler.get_job('maintenance') is not None
        first.configure()
        assert len(first.scheduler.get_jobs()) == 2
    finally:
        first.stop()
        second.stop()


def test_cli_serve_binds_localhost_without_reloader(monkeypatch, app):
    run = Mock()
    monkeypatch.setattr(app, 'run', run)
    monkeypatch.setattr(main, 'create_app', lambda: app)
    monkeypatch.setattr('sys.argv', ['main.py', 'serve', '--no-scheduler', '--no-startup-research'])
    main.main()
    run.assert_called_once()
    assert run.call_args.kwargs['host'] == '127.0.0.1'
    assert run.call_args.kwargs['debug'] is False
    assert run.call_args.kwargs['use_reloader'] is False


def test_cli_initialization_preserves_stored_data(monkeypatch, app, capsys):
    monkeypatch.setattr(main, 'create_app', lambda: app)
    monkeypatch.setattr('sys.argv', ['main.py', 'init-db'])
    main.main()
    assert 'Database initialized' in capsys.readouterr().out

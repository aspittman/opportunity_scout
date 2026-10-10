"""OpportunityScout local commands. Run from this project directory."""
import argparse
import os
import threading
from opportunityscout.app import create_app
from opportunityscout.services.scheduler import LocalScheduler


def main():
    parser = argparse.ArgumentParser(description='OpportunityScout: local income and career research')
    parser.add_argument('command', choices=['serve', 'init-db', 'research', 'maintain'], nargs='?', default='serve')
    parser.add_argument('--kind', choices=['income', 'network'])
    parser.add_argument('--no-scheduler', action='store_true')
    parser.add_argument('--no-startup-research', action='store_true')
    args = parser.parse_args()
    app = create_app()
    research = app.extensions['research']
    if args.command == 'init-db':
        print(f'Database initialized: {app.config["DATABASE"]}')
    elif args.command == 'research':
        print('Research finished (check dashboard history for provider results).' if research.run(args.kind) else 'Research is already running.')
    elif args.command == 'maintain':
        research.maintenance()
        print('Expiration and scoring refreshed.')
    else:
        scheduler = None
        if not args.no_scheduler:
            scheduler = LocalScheduler(research, app.config['DATABASE'] + '.scheduler.lock')
            if scheduler.start():
                app.extensions['scheduler'] = scheduler
            else:
                print('Another process owns scheduling; this process serves the dashboard only.')
        if not args.no_startup_research:
            threading.Thread(target=research.run, kwargs={'due_only': True}, daemon=True, name='startup-research').start()
        try:
            app.run(host='127.0.0.1', port=int(os.getenv('OPPORTUNITYSCOUT_PORT', '5000')), debug=False, use_reloader=False)
        finally:
            if scheduler:
                scheduler.stop()


if __name__ == '__main__':
    main()

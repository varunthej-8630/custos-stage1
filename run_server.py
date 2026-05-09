from web.server import start
import updater

if __name__ == '__main__':
    # Check for updates first
    updater.check_and_apply_updates()
    
    # Start the application
    start()

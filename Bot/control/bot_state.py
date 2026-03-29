# Bot/control/bot_state.py

class BotState:
    running = False
    entry_enabled = True
    close_all_flag = False
    risk = 1.0
    max_positions = 1
    last_command = None
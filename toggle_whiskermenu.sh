#!/bin/bash
# Toggle xfce4-popup-whiskermenu on Super_L key release

# Window ID of the whiskermenu popup
WINDOW_ID="0x600050"

# Check if the whiskermenu popup window is open
if xdotool search --onlyvisible --window "$WINDOW_ID" > /dev/null; then
    # If open, close the window
    xdotool windowactivate --sync "$WINDOW_ID" key --clearmodifiers Escape
else
    # If closed, open it
    xfce4-popup-whiskermenu

    # Wait for the window to open and move it to the desired position
    #sleep 0.5  # Adjust the delay if needed
    xdotool windowmove "$WINDOW_ID" 0 899
fi
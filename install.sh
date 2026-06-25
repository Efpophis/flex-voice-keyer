#!/bin/bash



if [ -x build.sh ]; then
    ./build.sh
fi

if [ -d dist ]; then    
    pushd dist
    sudo install -m755 wk2x_keyer /usr/local/bin
    popd
    sudo install -m644 wk2x_keyer.desktop /usr/local/share/applications
    sudo install -m644 wk2x_keyer_icon.png /usr/local/share/icons
    sudo update-desktop-database /usr/local/share/applications
else
    echo "nothing to install (dist doesn't exist)"
    exit 1
fi

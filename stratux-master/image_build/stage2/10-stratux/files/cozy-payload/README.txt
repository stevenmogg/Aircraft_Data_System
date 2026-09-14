Cozy Aircraft Data System — baked into the Stratux image
========================================================

This tree is copied to /cozy-data-system at image-build time.

After first flash, create the Python venv (offline wheels) and enable services:

  sudo /cozy-data-system/scripts/setup_fix_gateway.sh /tmp/fixgw-wheels
  sudo /cozy-data-system/scripts/setup_cozy_web.sh /cozy-data-system
  sudo /cozy-data-system/scripts/setup_historian_step0_1.sh

FIX stores aircraft units at ingest (feet, °F). See doco/fix_gateway_install.md.

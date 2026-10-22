include("$(PORT_DIR)/boards/manifest.py")

require("bundle-networking")

# Bluetooth
require("aioble")

# The intomind library.
package("intomind", base_path="$(BOARD_DIR)/../..")

# ComfyUI-NS-Util
[日本語README]()
A collection of nodes for ComfyUI.

This consolidates the previously created nodes into one package.

## Node Contents

### NS-FlexPreset Node
A node for batch managing int, float, and string parameters with presets

## Installation

### If you have [ComfyUI-Manager](https://github.com/ltdrdata/ComfyUI-Manager) installed
1. Click Main Menu -> Manager -> Install via Git URL
2. Paste the URL into the text box that appears at the top of the window and press OK  
    https://github.com/NakamuraShippo/ComfyUI-NS-Util
3. Once installation is complete, restart ComfyUI

### If you don't have [ComfyUI-Manager](https://github.com/ltdrdata/ComfyUI-Manager) installed
1. Navigate to ComfyUI's custom nodes directory (usually ComfyUI/custom_nodes/)
2. Clone this repository:  
`git clone https://github.com/NakamuraShippo/ComfyUI-NS-Util`
3. Restart ComfyUI
4. In ComfyUI\venv\Scripts, Shift+right-click -> Open terminal -> activate
  ```python
pip install pyyaml watchdog
  ```

## Usage

### NS-FlexPreset Node

1. **Add Node**: Find "NS Flex Preset" in the "NS" category of the node menu

2. **Create/Edit YAML Presets**:
   - YAML files are saved in `ComfyUI/custom_nodes/ComfyUI-NS-Util/nodes/presets/`
   - Example YAML structure:
   ```yaml
    positive prompt:
      type: string
      value: daytime sky nature dark blue galaxy bottle
    negative prompt:
      type: string
      value: text, watermark
    steps:
      type: int
      value: '22'
    cfg:
      type: float
      value: '4.55'
   ```

3. **Using in ComfyUI**:
   - Select a YAML file from select_yaml
   - Select or enter select_preset
   - The node automatically creates typed output ports for each value
   - Connect these outputs to other nodes in your workflow

4. **Editing Values in UI**:
   - Click "Add Value" to create new preset values
   - Change values directly on the node
     - For int/float, the input widget becomes a slider - click to input, drag left/right to adjust values
   - How to delete values:
     - Select key name in select_value -> Click Delete [key name] button
     - If Names are duplicated, the last entered value is kept and others are deleted
   - All changes are automatically saved to the YAML file
   - You can also edit YAML directly
     - If edited while ComfyUI is running, switch presets or refresh the browser

## Node Interface

- **select_yaml**: Choose from available YAML files
- **select_title**: Choose from existing preset titles in the selected YAML
- **input_title**: Input custom title (creates new if doesn't exist)
- **Value Panel**: Display and edit each preset value:
  - Name (editable)
  - Type selector (int/float/string)
  - Value input field
- **Add/Delete Buttons**: Manage preset values

## Requirements

- ComfyUI (0.3 or later recommended, other versions not tested)
- Python packages (automatically included with ComfyUI):
  - pyyaml
  - watchdog
  - aiohttp

## Roadmap

This is the first node in the NS-Util collection. Future additions planned:
 - [ManySliders](https://github.com/NakamuraShippo/ComfyUI-NS-ManySliders)
   - Will be redesigned to be switchable with presets before addition

## Contributing

Contributions are welcome! Feel free to submit pull requests or create issues for bugs and feature requests.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

If you encounter problems or have questions:
- Create an issue on GitHub
- [Nakamura Shippo lit.link](https://lit.link/nakamurashippo)

## Acknowledgments

- Thanks to the ComfyUI team for creating an amazing platform
- Thanks to AI animals for giving me ideas

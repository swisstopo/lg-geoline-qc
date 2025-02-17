# lg-geolines-qc
QGis plugins to assess quality of digitalized geological lines boundaries against reference dataset.


## Installation

To install this plugin, you can download the zip file from the [releases](https://github.com/procrastinatio/lg-geolines-qc/releases) page.

The direct download for the latest version at [here](https://github.com/procrastinatio/lg-geolines-qc/releases/latest).

Once downloaded, go to  `Plugins -> Install and Manage Plugins... -> Install from ZIP`  and select the file
you just donwloaded.

You can find the plugins directory by going to `Settings -> System -> Plugins`.


## Usage

Open the Plugin from the Menu bar

![Plugin menu](assets/Menu-Plugin.png)

In the following dialog, choose:
* The layer to check
* The reference layer, usually Geocover or TK500
* The buffer distance, usually 100 meters for Geocover, 500 meters for TK500. Optional, default is 500 meters
* The mask region (Alps, Prealps)

![Plugin Dialog](assets/Plugin-Dialog.png)

A new temporary file with the combined name of the tested layer will be added to the project,
with a new field `intersects` set to `True/False`

![the picture](assets/Results.png)
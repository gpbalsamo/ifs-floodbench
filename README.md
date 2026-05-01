# ifs-floodbench

## Overview

The **ifs-floodbench** project aims to share current progress in benchmarking flood events using Earth Observation datasets:

* **GFM (Sentinel-1)**
* **VIIRS (Suomi NPP, NOAA-20, NOAA-21)**

The objective is to support validation and accelerate the development of flood monitoring capabilities.

---

## Repository Structure

The repository contains a set of Python notebooks designed to support flood event analysis and benchmarking workflows.

---

## Notebooks

### 1. Flood Event Visualisation

Visualisation of flood events from Cama-Flood (CMF) model outputs (1, 3, 6, 15 arcmin resolutions tested).

* **Notebook:** `Notebooks/Rivers-Inundation-Forecast.ipynb`
* **Inputs:**

  * `flood_case` name
  * geographical `area`

---

### 2. Extraction of EO Flood Data

#### Sentinel-1 (GFM)

Extraction of flood extent from the **Global Flood Monitoring (GFM)** system (~20 m resolution).

* **Notebook:** `Notebooks/Extract_GFM_Inundation.ipynb`

#### VIIRS

Extraction of flood extent from **VIIRS** (~375 m resolution).

* **Notebook:** `Notebooks/Extract_VIIRS_Inundation.ipynb`

* **Environment requirement:**
  A Conda environment is required for GFM processing: gfm_env.yaml file included in the Notebooks directory.

* **Inputs:**

  * same `flood_case` name
  * same `area` definition

---

### 3. Benchmarking Framework

Comparison of CaMa-Flood model simulations against EO observations. Note the benchmark consider the model grid as the target to which interpolating observations. 
This choice was necessary due to the large discrepancy between model output and observations resolutions.

#### CMF vs GFM

* **Notebook:** `Notebooks/Bench_CMF_GFM_Inundation.ipynb`

#### CMF vs VIIRS

* **Notebook:** `Notebooks/Bench_CMF_VIIRS_Inundation.ipynb`

* **Inputs:**

  * consistent `flood_case` name across datasets

---

## Methodological Background

The general benchmarking framework is described in:

* A benchmarking framework for flood models using EO data https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2024MS004379 

---

## Requirements

Typical dependencies include:

* Python 3.x
* Metview
* xarray
* numpy
* matplotlib
* metview
* rasterio
* odc-stac (for EO data access)

Additional dependencies may be required for GFM processing (see environment file above).

---

## Usage Notes

* Ensure consistent **naming of flood cases** across all notebooks
* Use the same **geographical area definition** when comparing datasets
* Avoid committing large EO datasets to the repository

---

## Authors

Gianpaolo Balsamo
Calum Baugh
Kenka Tazi
Andreas Grafberger
ECMWF

---

## Future Work

* Extension to additional EO datasets
* Improved harmonisation across spatial resolutions
* Integration with Earth System Model workflows

---

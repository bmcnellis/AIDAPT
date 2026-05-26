
var aoi = ee.Geometry.Rectangle(
  [1535557.8379021066, -3957765.875192861,
   1536889.676893365,  -3956800.2729655616],
  'EPSG:3577',
  false          // geodesic = false (projected rectangle)
);

// Reproject to WGS84 for display / map centering
var aoiWGS84 = aoi.transform('EPSG:4326', 1);

Map.centerObject(aoiWGS84, 14);
Map.addLayer(aoiWGS84, {color: 'red'}, 'Area of Interest');

print('AOI area (km²):', aoi.area({maxError: 1, proj: 'EPSG:3577'}).divide(1e6));

var dem = ee.ImageCollection('AU/GA/AUSTRALIA_5M_DEM')
            .filterBounds(aoi)
            .mosaic()
            .clip(aoi);

var demBand = 'elevation';

var demStats = dem.select(demBand).reduceRegion({
  reducer: ee.Reducer.mean()
              .combine(ee.Reducer.stdDev(),  '', true)
              .combine(ee.Reducer.min(),     '', true)
              .combine(ee.Reducer.max(),     '', true)
              .combine(ee.Reducer.median(),  '', true)
              .combine(ee.Reducer.count(),   '', true),
  geometry: aoi,
  crs: 'EPSG:3577',
  scale: 5,          // native 5 m resolution
  maxPixels: 1e9
});

print('=== DEM Summary (AU/GA/AUSTRALIA_5M_DEM) ===', demStats);

var demVis = {
  min: dem.select(demBand).reduceRegion({
    reducer: ee.Reducer.percentile([2]), geometry: aoi, scale: 5, maxPixels: 1e9
  }).values().get(0),
  max: dem.select(demBand).reduceRegion({
    reducer: ee.Reducer.percentile([98]), geometry: aoi, scale: 5, maxPixels: 1e9
  }).values().get(0),
  palette: ['006633', 'E5FFCC', '662A00', 'D8D8D8', 'F5F5F5']
};
Map.addLayer(dem.select(demBand), demVis, 'DEM Elevation (5m)');

var hillshade = ee.Terrain.hillshade(dem.select(demBand));
Map.addLayer(hillshade, {min: 0, max: 255, opacity: 0.4}, 'Hillshade');

var ndviCollection = ee.ImageCollection('LANDSAT/COMPOSITES/C02/T1_L2_32DAY_NDVI')
                       .filterBounds(aoi);

// Helper: build annual mean NDVI image and compute zonal stats
var annualNDVI = function(year) {
  var start = ee.Date.fromYMD(year, 1, 1);
  var end   = ee.Date.fromYMD(year, 12, 31);

  var annual = ndviCollection
    .filterDate(start, end)
    .select('NDVI')
    .mean()
    .clip(aoi);

  var stats = annual.reduceRegion({
    reducer: ee.Reducer.mean()
                .combine(ee.Reducer.stdDev(),  '', true)
                .combine(ee.Reducer.min(),     '', true)
                .combine(ee.Reducer.max(),     '', true)
                .combine(ee.Reducer.median(),  '', true)
                .combine(ee.Reducer.count(),   '', true),
    geometry: aoi,
    crs: 'EPSG:3577',
    scale: 30,        // Landsat native resolution
    maxPixels: 1e9
  });

  return {image: annual, stats: stats, year: year};
};

// --- 2012 ---
var ndvi2012 = annualNDVI(2012);
print('=== NDVI Summary 2012 (Annual Mean of 32-Day Composites) ===', ndvi2012.stats);
Map.addLayer(
  ndvi2012.image,
  {min: 0, max: 1, palette: ['brown', 'yellow', 'darkgreen']},
  'NDVI Annual Mean 2012'
);

// --- 2025 ---
var ndvi2025 = annualNDVI(2025);
print('=== NDVI Summary 2025 (Annual Mean of 32-Day Composites) ===', ndvi2025.stats);
Map.addLayer(
  ndvi2025.image,
  {min: 0, max: 1, palette: ['brown', 'yellow', 'darkgreen']},
  'NDVI Annual Mean 2025'
);

var makeTimeSeries = function(year) {
  return ndviCollection
    .filterDate(
      ee.Date.fromYMD(year, 1, 1),
      ee.Date.fromYMD(year, 12, 31)
    )
    .select('NDVI')
    .map(function(img) {
      var mean = img.reduceRegion({
        reducer: ee.Reducer.mean(),
        geometry: aoi,
        crs: 'EPSG:3577',
        scale: 30,
        maxPixels: 1e9
      });
      return img.set('year', year)
                .set('NDVI_mean', mean.get('NDVI'));
    });
};

var ts2012 = makeTimeSeries(2012);
var ts2025 = makeTimeSeries(2025);

print(
  ui.Chart.feature.byFeature({
    features: ts2012,
    xProperty: 'system:time_start',
    yProperties: ['NDVI_mean']
  })
  .setChartType('LineChart')
  .setOptions({
    title: 'Mean NDVI — 32-Day Composites (2012)',
    hAxis: {title: 'Date', format: 'MMM'},
    vAxis: {title: 'Mean NDVI', minValue: 0, maxValue: 1},
    colors: ['#1b7837'],
    lineWidth: 2,
    pointSize: 4
  })
);

print(
  ui.Chart.feature.byFeature({
    features: ts2025,
    xProperty: 'system:time_start',
    yProperties: ['NDVI_mean']
  })
  .setChartType('LineChart')
  .setOptions({
    title: 'Mean NDVI — 32-Day Composites (2025)',
    hAxis: {title: 'Date', format: 'MMM'},
    vAxis: {title: 'Mean NDVI', minValue: 0, maxValue: 1},
    colors: ['#762a83'],
    lineWidth: 2,
    pointSize: 4
  })
);

var combined = ts2012.merge(ts2025);
print(
  ui.Chart.image.series({
    imageCollection: ndviCollection
      .filterDate('2012-01-01', '2012-12-31')
      .merge(ndviCollection.filterDate('2025-01-01', '2025-12-31'))
      .select('NDVI'),
    region: aoi,
    reducer: ee.Reducer.mean(),
    scale: 30,
    xProperty: 'system:time_start'
  })
  .setChartType('LineChart')
  .setOptions({
    title: 'NDVI Comparison: 2012 vs 2025 (32-Day Composites)',
    hAxis: {title: 'Date'},
    vAxis: {title: 'Mean NDVI', minValue: 0, maxValue: 1},
    lineWidth: 2,
    pointSize: 3
  })
);
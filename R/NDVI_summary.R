
library(dplyr)
library(ggplot2)

NDVI_result_file <- '../results/NDVI_results_2026-05-25.csv'

NDVI <- read.csv(NDVI_result_file) |>
  select(name, center_lon, center_lat, year, month, ndvi_mean, ndvi_stdDev, ndvi_median) |>
  na.omit()

ggplot(data = NDVI, aes(x = ndvi_mean, y = ndvi_median)) +
  geom_point() +
  theme_bw() +
  theme(axis.text = element_text(color = 'black')) +
  labs(x = 'Mean NDVI', y = 'Median NDVI', title = 'Mean/Median NDVI Correlation',
       subtitle = paste0('Pearson correlation: ', round(cor(NDVI$ndvi_mean, NDVI$ndvi_median, method = 'pearson'), 4))
  )
# No strong outliers, can use mean NDVI

NDVI <- NDVI |>
  arrange(name) |>
  rename('AOI' = name, 'center_lon_3577' = center_lon, 'center_lat_3577' = center_lat) |>
  mutate(month = sprintf('%02d', month)) |>
  mutate(date = as.Date(paste0(year, month, '15'), format = '%Y%m%d')) |>
  select(-ndvi_median, -year, -month)


for (i in seq_along(unique(NDVI$AOI))) {
  
  ii <- unique(NDVI$AOI)[i]
  NDVI_i <- NDVI[which(NDVI$AOI == ii), ]
  tit_i <- paste0('NDVI for AOI: ', ii)
  
  plot_i <- ggplot(data = NDVI_i, aes(x = date, y = ndvi_mean)) +
    geom_line() +
    scale_x_date(date_breaks = '1 year', date_labels = '%Y') +
    theme_bw() +
    theme(axis.text = element_text(color = 'black', angle = 45, hjust = 1)) +
    labs(x = 'Year', y = 'NDVI', title = tit_i)
  
  print(plot_i)
  
}

write.csv(NDVI, '../results/AIDAPT_NDVI_20260505.csv')

library(dplyr)

in_fl <- '../data/long_format_sites_20260527.csv'

d0 <- read.csv(in_fl)

# check year
in_fl |>
  read.csv() |>
  mutate(date = replace(date, notes == '201300526 some cloud', '2013/5/26')) |>
  mutate(year_check = as.integer(sapply(strsplit(date, '/'), \(xx) xx[1]))) |>
  mutate(year_filt = ifelse(year_check == year, T, F)) |>
  filter(year_filt == F) |>
  mutate(date_Date = as.Date(date, format = '%Y/%m/%d')) |>
  write.csv('long_format_check_year.csv', row.names = F)
  

d0 <- in_fl |>
  read.csv() |>
  mutate(notes = gsub('\\)|\\(|\\?', '', notes)) |>
  mutate(notes = gsub('\\. ', '', notes)) |>
  mutate(notes = tolower(notes)) |>
  mutate(notes = ifelse(notes == '', NA, notes)) |>
  mutate(observation_count = ifelse(is.na(observation_count), 1, observation_count)) |>
  mutate(date = replace(date, notes == '201300526 some cloud', '2013/5/26')) |>
  mutate(notes = gsub('201300526 ', '', notes)) |>
  mutate(notes = trimws(notes)) |>
  mutate(notes = gsub('onw', 'one', notes)) |>
  mutate(date = as.Date(date, format = '%Y/%m/%d')) |>
  mutate(image_id = format(date, format = '%Y%m%d')) |>
  mutate(group = gsub("\\,", '', group)) |>
  mutate(location = gsub("\\'", '', location)) |>
  rename('image_date' = date, 'image_count' = observation_count, 'QC_notes' = notes) |>
  select(group, location, site_id, 
         x_centre_4326, y_centre_4326, 
         xmin_4326, ymin_4326, xmax_4326, ymax_4326, 
         xmin_3577, ymin_3577, xmax_3577, ymax_3577,
         image_id, image_date, image_count, QC_notes)

write.csv(d0, '../data/long_format_sites_20260527_BM.csv', row.names = F)

select geo, region_name, population_weight
from {{ ref('halden_regions') }}

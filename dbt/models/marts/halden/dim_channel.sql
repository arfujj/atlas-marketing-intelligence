select channel, label, platform, channel_group, role, sort_order
from {{ ref('halden_channels') }}

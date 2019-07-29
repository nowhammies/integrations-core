# (C) Datadog, Inc. 2019
# All rights reserved
# Licensed under a 3-clause BSD style license (see LICENSE)
KNOWN_SECTION_DESCRIPTIONS = {
    'init_config': """\
All options defined here will be available to all instances.
""",
    'instances': """\
Every instance will be scheduled independent of the others.
""",
    'logs': """\
Log Section

type - required - Type of log input source (tcp / udp / file / windows_event)
port / path / channel_path - required - Set port if type is tcp or udp.
                                        Set path if type is file.
                                        Set channel_path if type is windows_event.
service - required - Name of the service that generated the log
source  - required - Attribute that defines which Integration sent the logs
sourcecategory - optional - Multiple value attribute. Used to refine the source attribute
tags - optional - Add tags to the collected logs

Discover Datadog log collection: https://docs.datadoghq.com/logs/log_collection/
""",
}

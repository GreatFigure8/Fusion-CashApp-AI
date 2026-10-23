"""The roles of the two money-path stations. The only module here that defines ``ROLES``."""

from cashapp.pipeline.roles import RoleSpec
from cashapp.pipeline.runner import consumer_role
from cashapp.stations.apply.runner import ApplyRunner
from cashapp.stations.match_lines.runner import MatchLinesRunner

ROLES: list[RoleSpec] = [consumer_role(MatchLinesRunner), consumer_role(ApplyRunner)]

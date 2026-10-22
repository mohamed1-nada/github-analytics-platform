{{ config(materialized='view') }}

select
    repository_id,
    week,
    total_commits,
    sunday_commits,
    monday_commits,
    tuesday_commits,
    wednesday_commits,
    thursday_commits,
    friday_commits,
    saturday_commits,
    to_timestamp(week) at time zone 'utc' as week_start
from {{ source('raw', 'commit_activity') }}

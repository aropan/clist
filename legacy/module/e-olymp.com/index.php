<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $url = 'https://api.eolymp.com/spaces/00000000-0000-0000-0000-000000000000/graphql';
    $list_contests_query = <<<'EOD'
query  ListContests($first: Int,  $offset: Int, $filters: JudgeContestFilter)  {
    contests(first: $first,  offset: $offset, filters: $filters, extra: ["STAFF"])  {
        nodes  {
            id
            name
            format
            duration
            startsAt
            endsAt
            scoring  {
                showScoreboard
                attemptPenalty
                freezingTime
                allowUpsolving
                tieBreaker
            }
            upsolve  {
                freeUpsolve
                virtualUpsolve
            }
            scoreboard  {
                visibility
                attemptPenalty
                freezingTime
                unfreezeDelay
                tieBreaker
                modes
            }
            staff {
                edges {
                    node {
                        id
                    }
                    role
                    displayName
                }
            }
        }
        pageInfo  {
            hasNextPage
        }
        totalCount
    }
}
EOD;

    $count = 100;
    $offset = 0;
    for (;;) {
        $request_data  = json_encode(['query' => $list_contests_query, 'variables' => ['first' => $count, 'offset' => $offset]]);
        $data = curlexec($url, $request_data, ['json_output' => true]);
        if (!isset($data['data']['contests'])) {
            trigger_error('data = ' . json_encode($data), E_USER_WARNING);
            break;
        }
        $data = $data['data']['contests'];
        foreach ($data['nodes'] as $node) {
            $contests[] = array(
                'start_time' => array_pop_assoc($node, 'startsAt'),
                'end_time' => array_pop_assoc($node, 'endsAt'),
                'duration_in_secs' => array_pop_assoc($node, 'duration'),
                'title' => array_pop_assoc($node, 'name'),
                'url' => $URL . '/' . $node['id'],
                'rid' => $RID,
                'host' => $HOST,
                'timezone' => $TIMEZONE,
                'kind' => array_pop_assoc($node, 'format'),
                'key' => array_pop_assoc($node, 'id'),
                'info' => ['parse' => $node],
            );
        }
        if (!$data['pageInfo']['hasNextPage'] || !isset($_GET['parse_full_list'])) {
            break;
        }
        $offset += $count;
    }
?>

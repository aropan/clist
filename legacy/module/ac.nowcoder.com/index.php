<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $seen = array();

    function process_url($url) {
        global $contests, $RID, $HOST, $TIMEZONE;
        global $seen;

        $page = curlexec($url);
        preg_match_all('#<div[^>]*data-id="(?P<id>[^"]*)"[^<]*data-json="(?P<data>[^"]*)"[^>]*>#', $page, $matches, PREG_SET_ORDER);
        $n_parsed = 0;

        foreach ($matches as $_ => $match) {
            $data = html_entity_decode($match['data']);
            $data = html_entity_decode($data);
            $data = json_decode($data, true);

            $type = pop_item($data, 'type');
            if ($type == 0) {
                $kind = 'ACM';
                $standings_kind = 'icpc';
            } elseif ($type == 3) {
                $kind = 'IOI';
                $standings_kind = 'scoring';
            } elseif ($type == 2) {
                $kind = 'OI';
                $standings_kind = 'scoring';
            } else {
                $kind = null;
                $standings_kind = null;
            }

            $title = html_entity_decode(pop_item($data, 'contestName'));
            if ($kind) {
                $title .= " [$kind]";
            }

            $key = pop_item($data, 'contestId');

            $contest = [
                'title' => $title,
                'start_time' => pop_item($data, 'contestStartTime') / 1000,
                'end_time' => pop_item($data, 'contestEndTime') / 1000,
                'duration' => pop_item($data, 'contestDuration') / 1000 / 60,
                'url' => "https://ac.nowcoder.com/acm/contest/{$key}",
                'key' => $key,
                'rid' => $RID,
                'host' => $HOST,
                'timezone' => $TIMEZONE,
                'info' => ['parse' => $data],
            ];

            if ($standings_kind) {
                $contest['standings_kind'] = $standings_kind;
            }

            $contests[] = $contest;

            if (!isset($seen[$key])) {
                $seen[$key] = true;
                $n_parsed += 1;
            }
        }
        return $n_parsed;
    }

    process_url($URL);

    $page = 1;
    $base_url = parse_schema_host($URL) .  '/acm/contest/vip-end-index?orderType=DESC';

    for ($page = 1; ; $page++) {
        $url = $base_url . "&page=$page";
        $ok = process_url($url);

        if (!$ok || !isset($_GET['parse_full_list'])) {
            break;
        }
    }
?>

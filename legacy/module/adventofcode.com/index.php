<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $page = curlexec($URL);
    if (!preg_match('/server_eta\s*=\s*(?<eta>[0-9]+)/', $page, $match)) {
        return;
    }
    $eta = intval($match['eta']);

    if (!preg_match('#<title>(?<title>[^<]*)</title>#', $page, $match)) {
        return;
    }
    $stage_title = $match['title'];

    if (!preg_match('#day-?(?<day>[0-9]+).*day-new#', $page, $match)) {
        return;
    }
    $day = $match['day'];

    $year = date('Y');

    $start_time = time() + $eta;
    $start_time = round($start_time / 60) * 60;
    $title = "$stage_title. Day $day";

    $contests[] = array(
        'start_time' => $start_time,
        'duration' => '00:00',
        'title' => $title,
        'url' => url_merge($URL, "/$year"),
        'host' => $HOST,
        'rid' => $RID,
        'timezone' => 'UTC',
        'key' => $title,
    );

    $stage_start_time = date('Y-m-01 H:i:s', $start_time);
    $stage_end_time = date('Y-m-26 H:i:s', $start_time);
    $contest = array(
        'start_time' => $stage_start_time,
        'end_time' => $stage_end_time,
        'title' => $stage_title,
        'url' => url_merge($URL, "/$year/leaderboard"),
        'key' => slugify($stage_title),
        'info' => array('_inherit_stage' => true),
        'host' => $HOST,
        'timezone' => 'UTC',
        'rid' => $RID,
    );
    $contests[] = $contest;

    while (isset($_GET['parse_full_list'])) {
        $year -= 1;
        $url = "https://adventofcode.com/$year";
        $page = curlexec($url);

        if (response_code() == 404) {
            break;
        }

        if (!preg_match('#<title>(?<title>[^<]*)</title>#', $page, $match)) {
            return;
        }
        $name = $match['title'];

        preg_match_all('#<a[^>]*aria-label="(?P<label>[^"]*)"[^>]*href="(?P<href>[^>]*/day/[^>]*)"[^>]*class="calendar-day(?P<day>[0-9]+)"[^>]*>#', $page, $matches, PREG_SET_ORDER);
        foreach ($matches as $match) {
            $day = $match['day'];
            $title = "$name. {$match['label']}";
            $contests[] = array(
                'start_time' => "$day.12.$year 00:00",
                'duration' => '00:00',
                'title' => $title,
                'url' => url_merge($url, $match['href']),
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $title
            );
        }
    }

    if (DEBUG) {
        print_r($contests);
    }
?>

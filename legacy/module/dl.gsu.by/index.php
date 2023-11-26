<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $results_url = url_merge($URL, '/olymp/info/allgomel.asp');
    $schedule_page = curlexec($results_url);

    preg_match_all('#<div[^>]*YearLine[^>]*>[^<0-9]*(?P<year>[0-9]+)[^>]*<small>\s*<a[^>]*href=[\'"](?P<href>[^\'"]*)[\'"][^>]*>[^<]*</a>[^0-9]*(?P<date>[-0-9. ]*),[^<]*</small>#', $schedule_page, $matches, PREG_SET_ORDER);

    foreach ($matches as $idx => $match) {
        $year = $match['year'];
        $season = $year - 1 . "-" . $year;
        $title = "Заключительный этап республиканской олимпиады по учебному предмету «Информатика» " . $season;
        list($start_time, $end_time) = explode('-', $match['date']);
        $url = url_merge($results_url, $match['href']);
        $url = str_replace('_', '.', $url);

        $contests[] = array(
            'start_time' => $start_time,
            'end_time' => $end_time,
            'duration' => '10:00',
            'title' => $title,
            'url' => $results_url,
            'key' => $title,
            'standings_url' => $url,
            'host' => $HOST,
            'timezone' => $TIMEZONE,
            'rid' => $RID,
            'skip_update_key' => true,
            'skip_check_time' => $idx < 3,
            'info' => array("default_problem_full_score" => 100, "series" => "byio"),
        );
    }
?>

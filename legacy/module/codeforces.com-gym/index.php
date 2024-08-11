<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $page = curlexec($URL);
    /* old regex for parse from page
    #<tr[^>]*data-contestId="(?<key>[^"]*)"[^>]*>[^<]*<td>(?<title>.*?)</td>[^<]*<td>[^<]*(?:-|<a href="http://timeanddate\.com/[^"]*" .*?>(?<start_time>[^<]*)</a>)[^<]*</td>[^<]*<td>(?<duration>[^<]*)</td>#s
     */
    preg_match_all(
        '#<tr[^>]*data-contestId="(?<key>[^"]*)"[^>]*>.*?Prepared\s*by[^<]*<a[^>]*>(?P<author>.*?)</a>#s',
        $page,
        $matches,
        PREG_SET_ORDER
    );
    $authors = array();
    foreach ($matches as $match) {
        $authors[$match['key']] = $match['author'];
    }

    $url = 'http://codeforces.com/api/contest.list?gym=true&lang=en';
    $json = curlexec($url, NULL, array('json_output' => true));
    if (!is_array($json)) {
        return;
    }
    if (strpos($url, 'gym=true') === false) {
        trigger_error("Not found gym in $url", E_USER_WARNING);
        return;
    }
    if ($json['status'] != 'OK') {
        $json_str = print_r($json, true);
        trigger_error("status = {$json['status']}, json = $json_str", E_USER_WARNING);
        return;
    }

    foreach ($json['result'] as $c) {
        if (isset($c['startTimeSeconds'])) {
            $start_time = $c['startTimeSeconds'];
        } else {
            if (!empty($c['season'])) {
                list($year, $_) = explode('-', $c['season']);
            } else if (preg_match('#(?P<year>^[0-9]{4}\b|\b[0-9]{4}$)#', $c['name'], $match)) {
                $year = $match['year'];
            } else {
                continue;
            }
            $start_time = strtotime("$year-09-02");
            if ($start_time > time()) {
                $start_time = strtotime(($year - 1) . "-09-02\n");
            }
        }
        $title = $c['name'];
        if (isset($authors[$c['id']])) {
            $title .= '. ' . $authors[$c['id']];
        }
        $contests[] = array(
            'start_time' => $start_time,
            'duration' => $c['durationSeconds'] / 60,
            'title' => $title,
            'url' => 'http://codeforces.com/gym/' . $c['id'],
            'host' => $HOST,
            'key' => $c['id'],
            'rid' => $RID,
            'timezone' => $TIMEZONE
        );
    }

    if ($RID == -1) {
        print_r($contests);
    }
?>

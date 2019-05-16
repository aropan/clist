<?php
    require_once dirname(__FILE__) . '/../../config.php';

    if (!isset($URL)) $URL = 'http://codeforces.com/gyms';
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'Europe/Moscow';
    if (!isset($contests)) $contests = array();

    $page = curlexec($URL);
    /* old regex for parse from page
    #<tr[^>]*data-contestId="(?<key>[^"]*)"[^>]*>[^<]*<td>(?<title>.*?)</td>[^<]*<td>[^<]*(?:-|<a href="http://timeanddate\.com/[^"]*" .*?>(?<start_time>[^<]*)</a>)[^<]*</td>[^<]*<td>(?<duration>[^<]*)</td>#s
     */
    preg_match_all(
        '#<tr[^>]*data-contestId="(?<key>[^"]*)"[^>]*>.*?Подготовил[^<]*<a[^>]*>(?P<author>.*?)</a>#s',
        $page,
        $matches,
         PREG_SET_ORDER
    );
    $authors = array();
    foreach ($matches as $match) {
        $authors[$match['key']] = $match['author'];
    }

    $url = 'http://codeforces.com/api/contest.list?gym=true';
    $json = curlexec($url, NULL, array('json_output' => true));

    $json['status'] == 'OK' or trigger_error("status = '${json['status']}' for $url");

    foreach ($json['result'] as $c) {
        if (!isset($c['startTimeSeconds'])) {
            continue;
        }
        $title = $c['name'];
        if (isset($authors[$c['id']])) {
            $title .= '. ' . $authors[$c['id']];
        }
        $contests[] = array(
            'start_time' => $c['startTimeSeconds'],
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

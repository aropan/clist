<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "https://www.hackerrank.com/rest/contests/upcoming";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'UTC';
    if (!isset($contests)) $contests = array();

    $page = curlexec($URL);

    if (!preg_match("/^\{.*\}$/m", $page, $match)) {
        return;
    }
    $json = json_decode($match[0], true);

    foreach ($json['models'] as $model)
    {
        $contests[] = array(
            'start_time' => date('r', $model['epoch_starttime']),
            'end_time' => date('r', $model['epoch_endtime']),
            'title' => $model['name'],
            'url' => 'https://www.hackerrank.com/contests/' . $model['slug'],
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => 'UTC',
            'key' => $model['id']
        );
    }
    if ($RID == -1) {
        print_r($contests);
    }
?>

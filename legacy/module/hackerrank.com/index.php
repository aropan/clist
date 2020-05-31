<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $urls = array($URL, 'https://www.hackerrank.com/rest/contests/college');
    foreach ($urls as $url) {
        $json = curlexec($url, NULL, array('json_output' => true));
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
    }
    if ($RID == -1) {
        print_r($contests);
    }
?>

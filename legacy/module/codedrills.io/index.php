<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $url = 'https://api.prod.codedrills.io/site/io.codedrills.proto.site.ContentViewService/UserContentPreviews';
    $page = curlexec($url, 'AAAAAAUSAQMwAQ==', array("http_header" => array('Content-Type: application/grpc-web-text', 'Accept: application/grpc-web-text'), 'no_header' => true));
    $file = tmpfile();
    fwrite($file, $page);
    $path = stream_get_meta_data($file)['uri'];
    $python_bin = getenv('PYTHON_BIN');
    exec($python_bin . " " . dirname(__FILE__) . "/decode.py $path $path");
    $data = json_decode(file_get_contents($path), true);
    if (!is_array($data) || !is_array($data[1])) {
        trigger_error("Expected array [1]", E_USER_WARNING);
        return;
    }

    foreach ($data[1] as $c) {
        $c = $c[1];
        if (is_array($c[3]) || is_array($c[4]) || is_array($c[11][6][6]) || is_array($c[11][6][7])) {
            continue;
        }
        $title = trim(strval($c[3]));
        $slug = trim(strval($c[4]));
        $contests[] = array(
            'start_time' => $c[11][6][6],
            'end_time' => $c[11][6][7],
            'title' => $title,
            'url' => url_merge($URL, '/contests/' . $slug),
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => strval($c[1]),
        );
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>

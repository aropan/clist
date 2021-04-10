<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $url = 'https://api.prod.codedrills.io/site/io.codedrills.proto.site.ContentViewService/UserContentPreviews';
    $page = curlexec($url, 'AAAAAAUSAQMwAQ==', array("http_header" => array('Content-Type: application/grpc-web-text', 'Accept: application/grpc-web-text'), 'no_header' => true));
    $data = base64_decode($page);
    $a = str_split(substr($data, 0, 5));
    $size = 0;
    foreach ($a as $val) {
        $size = ($size << 8) + ord($val);
    }

    $data = substr($data, 5, $size);

    $file = tmpfile();
    fwrite($file, $data, $size);
    $path = stream_get_meta_data($file)['uri'];

    exec("protoc --decode_raw < $path", $output);
    $output = implode("\n", $output);
    $output = preg_replace('#^1 {#m', '-', $output);
    $output = preg_replace('#([0-9]+) {#', '\1:', $output);
    $output = preg_replace('#^\s*}\s*$#m', '', $output);

    $data = yaml_parse($output);

    foreach ($data as $c) {
        $c = $c[1];
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

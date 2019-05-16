<?php
    //require_once "credentials.php";
    isset($_GET["error"]) && die("ERROR: " . $_GET["error"]);
    assert(isset($_GET["code"]));

    //$params = array(
        //"code" => $_GET["code"],
        //"client_id" => CLIENT_ID,
        //"client_secret" => CLIENT_SECRET,
        //"redirect_uri" => "http://clist.by/api/google-calendar/exchange-code.php",
        //"grant_type" => "authorization_code"
    //);
    //$url = "https://www.googleapis.com/oauth2/v3/token";

    //$cid = curl_init();
    //curl_setopt($cid, CURLOPT_RETURNTRANSFER, true);
    //curl_setopt($cid, CURLOPT_SSL_VERIFYPEER, false);
    //curl_setopt($cid, CURLOPT_URL, $url);
    //curl_setopt($cid, CURLOPT_POST, true);
    //curl_setopt($cid, CURLOPT_POSTFIELDS, http_build_query($params));
    //$json = curl_exec($cid);
    //$http_code = curl_getinfo($cid, CURLINFO_HTTP_CODE);
    //$http_code != 200 && die("ERROR: " . "http code not equal 200, found " . $http_code . ", response:\n" . $json);
    //file_put_contents("token", $json);
    //curl_close($cid);

    $file_code = dirname(__file__) . "/code";
    file_put_contents($file_code, $_GET["code"]);
?>

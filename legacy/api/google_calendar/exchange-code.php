<?php
    isset($_GET["error"]) && die("ERROR: " . $_GET["error"]);
    assert(isset($_GET["code"]));
    $file_code = dirname(__file__) . "/code";
    file_put_contents($file_code, $_GET["code"]);
    chmod($file_code, 0666);
?>

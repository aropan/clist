<?php
    ini_set("display_errors", 1);
    ini_set("display_startup_errors", 1);
    ini_set('error_reporting', E_ALL);
//    ini_set("max_execution_time", 0);

    define("DEBUG", isset($_GET['debug']) && isset($_SERVER['SHELL']) && $_SERVER['SHELL'] == '/bin/bash');
    define("CACHE", DEBUG);
    define("CACHEDIR", dirname(__FILE__) . "/cache");

    require_once "db.class.php";
    require_once "libs/smarty/libs/Smarty.class.php";
    date_default_timezone_set("UTC");
//    var_dump(setlocale(LC_ALL,"ru_RU.UTF8"));

    $smarty = new Smarty();

    $smarty->template_dir = 'smarty/templates/';
    $smarty->compile_dir = 'smarty/compile/';
    $smarty->cache_dir = 'smarty/cache/';
    $smarty->caching = 1500;

    $files = glob(CACHEDIR . "/*");
    $now = time();
    foreach ($files as $file) {
        if (is_file($file)) {
            if ($now - filemtime($file) >= 60 * 60 * 24 * 14) { // 14 days
                unlink($file);
            }
        }
    }

    define("LOGFILE", dirname(__FILE__) . "/logs/working/index.txt");
    define("COUNTLINEINLOGFILE", 10000);
    define("LOGREMOVEDDIR", dirname(__FILE__) . '/logs/removed/');

    foreach (array(CACHEDIR, dirname(LOGFILE), LOGREMOVEDDIR) as $dir) {
        if (!file_exists($dir)) {
            mkdir($dir);
            chmod($dir, 0777);
        }
    }

    define("CALENDARCREDENTIALSFILE", dirname(__FILE__) . "/api/google_calendar/credentials");

    require_once "helper.php";
?>

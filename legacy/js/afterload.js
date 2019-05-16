    <script type="text/javascript">
        var pageLoadTime = (new Date()).getTime();
        countDown();

        var a = document.getElementsByClassName('add');
        if (a)
        {
            for (i = 0; i < a.length; i++)
                a[i].onchange = addValueChange;
            addValueChange();
        }
    </script>


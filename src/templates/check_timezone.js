<script type="text/javascript">
    var time = new Date();
    var offset = -time.getTimezoneOffset()
    if (Math.abs(offset - {{offset}}) > 1e-6) {
        $.ajax({
            type: "GET",
            url: "{% url 'clist:main' %}",
            data: "timezone=" + offset + "&update",
            success: function(data) {
                if (data == "reload") {
                    location.reload()
                } else if (data == "accepted") {
                    $.notify("Warning! Timezone is set incorrectly. Please reload page.", "warn")
                } else {
                    $.notify(data, "error")
                }
            }
        });
    }
</script>

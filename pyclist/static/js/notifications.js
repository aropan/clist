$(function() {
    $('.notice.alert').on('click', 'button.close', function() {
        var $this = $(this)
        $.ajax({
            url: $this.attr('data-url'),
            success: function() {
                $this.parent().slideUp(500, function() {
                    $(this).remove()
                })
            },
        })
    })
})

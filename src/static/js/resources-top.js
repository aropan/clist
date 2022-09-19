function resources_top_setup_hover() {
  $(".to-hover[data-coder]")
    .hover(
      function() {
        var coder = $(this).attr('data-coder')
        $("[data-coder='" + coder + "']").addClass('hover')
      },
      function() {
        var coder = $(this).attr('data-coder')
        $("[data-coder='" + coder + "']").removeClass('hover')
      },
    )
    .click(
      function() {
        var coder = $(this).attr('data-coder')
        var elements = $("[data-coder='" + coder + "']")
        if ($(this).hasClass('fixed')) {
          elements.removeClass('fixed')
        } else {
          elements.addClass('fixed')
        }
      }
    )
    .removeClass('to-hover')
}

$(resources_top_setup_hover)

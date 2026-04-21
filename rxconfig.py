import reflex as rx

config = rx.Config(
    app_name="GraphVision",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
    ]
)

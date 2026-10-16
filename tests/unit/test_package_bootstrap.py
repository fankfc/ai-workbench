def test_backend_package_is_importable():
    import app

    assert app.__name__ == "app"

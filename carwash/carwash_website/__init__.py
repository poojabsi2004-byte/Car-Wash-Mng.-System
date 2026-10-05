from . import controllers
from . import models


def _set_homepage_url(env):
    # website.default_website is noupdate=True in the website module's own seed
    # data, so a plain XML <record> update is silently skipped by the data loader -
    # only a direct ORM write (here, via post_init_hook) actually takes effect.
    website = env.ref("website.default_website", raise_if_not_found=False)
    if not website:
        return
    if not website.homepage_url:
        website.homepage_url = "/car-wash/home"
    # 'b2b' (invitation-only, the default) hides the "Sign up" link on /web/login -
    # customers hitting the booking flow without an account would have no visible
    # way to create one. 'b2c' (free sign up) shows both Log In and Sign Up.
    if website.auth_signup_uninvited == "b2b":
        website.auth_signup_uninvited = "b2c"

import UIKit
import Capacitor

class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }

        window = UIWindow(windowScene: windowScene)
        window?.rootViewController = GuestAppContainer()
        window?.makeKeyAndVisible()

        SceneDelegateProxy.shared.scene(scene, willConnectTo: session, options: connectionOptions)
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        SceneDelegateProxy.shared.scene(scene, openURLContexts: URLContexts)
    }

    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        SceneDelegateProxy.shared.scene(scene, continue: userActivity)
    }
}

// Keep the entire guest experience inside UIKit's safe area, including lateral
// camera/status regions on compact and folded displays. No identity permissions.
private final class GuestAppContainer: UIViewController {
    private let content = CAPBridgeViewController()
    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = UIColor(red: 246/255, green: 248/255, blue: 252/255, alpha: 1)
        addChild(content)
        let webContent = content.view!
        webContent.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(webContent)
        let safe = view.safeAreaLayoutGuide
        NSLayoutConstraint.activate([
            webContent.leadingAnchor.constraint(equalTo: safe.leadingAnchor),
            webContent.trailingAnchor.constraint(equalTo: safe.trailingAnchor),
            webContent.topAnchor.constraint(equalTo: safe.topAnchor),
            webContent.bottomAnchor.constraint(equalTo: safe.bottomAnchor)
        ])
        content.didMove(toParent: self)
    }
    override var childForStatusBarStyle: UIViewController? { content }
    override var childForStatusBarHidden: UIViewController? { content }
    override var supportedInterfaceOrientations: UIInterfaceOrientationMask { content.supportedInterfaceOrientations }
}
